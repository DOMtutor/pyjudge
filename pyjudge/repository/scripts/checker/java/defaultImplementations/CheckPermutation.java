package defaultImplementations;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.PriorityQueue;

import framework.CheckerInterface;

/**
 * Implementation of
 * {@link framework.CheckerInterface#checkCase(ArrayList, ArrayList, ArrayList)}
 *
 * checks whether for solution and program output the number of lines matches
 * and in the program output, the lines are a permutation of the solution output
 *
 * @author Philipp Hoffmann
 */
public interface CheckPermutation extends CheckerInterface {
  int SINGLE_LINE = 1;
  int MULTI_LINE = 2;

  /**
   * checks whether for solution and program output the number of lines
   * matches and in the program output, the lines are a permutation of the
   * solution output
   */
  @Override
  default void checkCase(ArrayList<String> in, ArrayList<String> prog,
      ArrayList<String> out) {

    PriorityQueue<String> outElements = new PriorityQueue<>();
    PriorityQueue<String> progElements = new PriorityQueue<>();

    if (permutationType() == SINGLE_LINE) {
      outElements.addAll(Arrays.asList(out.get(0).split(" ")));
      progElements.addAll(Arrays.asList(prog.get(0).split(" ")));
    } else if (permutationType() == MULTI_LINE) {
      outElements.addAll(out);
      progElements.addAll(prog);
    }

    if (outElements.size() != progElements.size()) {
      reportError("Incorrect number of outputs", outElements.size(),
          progElements.size());
      return;
    }
    while (!outElements.isEmpty()) {
      String outString = outElements.poll();
      String progString = progElements.poll();
      if (!outString.equals(progString)) {
        reportError("Not a permutation! First difference:", outString,
            progString);
        break;
      }
    }
  }

  /**
   * This function is used to decide which kind of permutation should be
   * checked. Possible permutations are:
   * <ul>
   * <li>
   * CheckPermutation.SINGLE_LINE = single line, elements separated by spaces</li>
   * <li>
   * CheckPermutation.MULTI_LINE = multiple lines, one element per line</li>
   * </ul>
   *
   * @return the desired permutation type
   */
  int permutationType();
}
